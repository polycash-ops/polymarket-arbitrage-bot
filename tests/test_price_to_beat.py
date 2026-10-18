"""Tests for Phase A Price-to-Beat eligibility (fixture only)."""

from __future__ import annotations

import unittest

from price_to_beat import extract_price_to_beat, reject_non_authoritative_fallbacks


def _market(**overrides):
    terms = {
        "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
        "horizon": "15m",
        "indexSymbol": "BRTI",
        "windowStart": "2026-10-17T19:00:00Z",
        "windowEnd": "2026-10-17T19:15:00Z",
        "priceToBeat": {"value": "81453.25", "currency": "USD"},
        "asset": {"assetClass": "ASSET_CLASS_CRYPTO", "symbol": "btc"},
    }
    if "assetPriceTerms" in overrides:
        patch = overrides.pop("assetPriceTerms")
        if patch is None:
            terms = None
        else:
            terms.update(patch)
    base = {
        "slug": "cpc-btc-updown-15m-2026-10-17-1900z",
        "assetPriceTerms": terms,
    }
    base.update(overrides)
    return base


class TestPriceToBeat(unittest.TestCase):
    def test_available_when_authoritative_field_present(self):
        r = extract_price_to_beat(_market(), provenance_trusted=True)
        self.assertEqual(r.status, "AVAILABLE")
        self.assertEqual(r.value, 81453.25)
        self.assertEqual(r.currency, "USD")
        self.assertEqual(r.source_field, "assetPriceTerms.priceToBeat")
        self.assertIsNone(r.reason)

    def test_unavailable_when_null(self):
        m = _market()
        m["assetPriceTerms"]["priceToBeat"] = None
        r = extract_price_to_beat(m)
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "price_to_beat_null")
        self.assertIsNone(r.value)

    def test_unavailable_when_missing_terms(self):
        r = extract_price_to_beat({"slug": "x"})
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "missing_asset_price_terms")

    def test_unavailable_wrong_horizon(self):
        r = extract_price_to_beat(_market(assetPriceTerms={"horizon": "1h"}))
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "not_15m_horizon")

    def test_unavailable_above_below_type(self):
        r = extract_price_to_beat(
            _market(assetPriceTerms={"marketType": "ASSET_PRICE_MARKET_TYPE_ABOVE_BELOW"})
        )
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "not_up_down_market_type")

    def test_fail_closed_on_missing_brti(self):
        r = extract_price_to_beat(_market(assetPriceTerms={"indexSymbol": "OTHER"}))
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "index_symbol_unverified_or_mismatch")

    def test_allow_unverified_index_still_not_authoritative(self):
        """allow_unverified_index must not promote to AVAILABLE."""
        r = extract_price_to_beat(
            _market(assetPriceTerms={"indexSymbol": None}),
            allow_unverified_index=True,
            require_brti=False,
        )
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "index_symbol_unverified_or_mismatch")

    def test_non_usd_currency_rejected(self):
        r = extract_price_to_beat(
            _market(assetPriceTerms={"priceToBeat": {"value": "81453.25", "currency": "EUR"}}),
            provenance_trusted=True,
        )
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "price_to_beat_currency_not_usd")

    def test_non_positive_rejected(self):
        r = extract_price_to_beat(
            _market(assetPriceTerms={"priceToBeat": {"value": "-1", "currency": "USD"}}),
            provenance_trusted=True,
        )
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "price_to_beat_not_positive_finite")

    def test_non_btc_asset_rejected(self):
        r = extract_price_to_beat(
            _market(assetPriceTerms={"asset": {"symbol": "ETH"}}),
            provenance_trusted=True,
        )
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "not_btc_asset")

    def test_missing_window_bounds(self):
        r = extract_price_to_beat(
            _market(assetPriceTerms={"windowStart": None, "windowEnd": None})
        )
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "missing_window_bounds")

    def test_reject_non_authoritative_fallbacks(self):
        warnings = reject_non_authoritative_fallbacks(
            {"strike": 80000, "tradingReferencePx": 81000, "priceToBeat": None}
        )
        self.assertTrue(any("strike" in w for w in warnings))
        self.assertTrue(any("tradingReferencePx" in w for w in warnings))

    def test_string_value_rejected_without_currency_object(self):
        m = _market()
        m["assetPriceTerms"]["priceToBeat"] = "82000.50"
        r = extract_price_to_beat(m, provenance_trusted=True)
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "missing_price_to_beat_currency")

    def test_unknown_provenance_never_available(self):
        r = extract_price_to_beat(_market(), provenance_trusted=False)
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "metadata_source_unverified")

    def test_missing_asset_rejected(self):
        r = extract_price_to_beat(
            _market(assetPriceTerms={"asset": {}}),
            provenance_trusted=True,
        )
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "missing_btc_asset")

    def test_trusted_path_available(self):
        r = extract_price_to_beat(_market(), provenance_trusted=True)
        self.assertEqual(r.status, "AVAILABLE")
        self.assertEqual(r.value, 81453.25)



if __name__ == "__main__":
    unittest.main()
