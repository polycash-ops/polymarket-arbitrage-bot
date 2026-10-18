"""Dashboard integration regressions for Phase A Price-to-Beat safety.

Flask is not required: these tests verify source transformations and the
parser contract. Full Flask route tests are marked NOT RUN when Flask is absent.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from price_to_beat import extract_price_to_beat, reject_non_authoritative_fallbacks


class TestDashboardPTBSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "dashboard.py").read_text()

    def test_dashboard_compiles(self):
        ast.parse(self.src)

    def test_source_does_not_alias_reference_price_as_price_to_beat(self):
        self.assertNotIn(
            "->>'reference_price','')::double precision AS price_to_beat",
            self.src,
        )
        self.assertIn("AS observation_reference_price", self.src)

    def test_source_imports_extract_price_to_beat(self):
        self.assertIn("from price_to_beat import extract_price_to_beat", self.src)

    def test_frontend_requires_available_status(self):
        self.assertIn('price_to_beat_status==="AVAILABLE"', self.src)
        self.assertNotIn(
            'x.price_to_beat==null?"—":usd(x.price_to_beat)',
            self.src,
        )

    def test_annotation_block_present(self):
        self.assertIn("authoritative_metadata_not_supplied_to_dashboard", self.src)
        self.assertIn("price_to_beat_status", self.src)
        self.assertIn("observation_reference_price", self.src)

    def test_current_contract_attaches_ptb_payload(self):
        self.assertIn('result["price_to_beat"]', self.src)
        self.assertIn("extract_price_to_beat(", self.src)
        self.assertIn("provenance_trusted=False", self.src)

    def test_legacy_reference_price_populated_target_unavailable(self):
        market = {"slug": "cpc-btc-updown-15m-x", "reference_price": 81000.0}
        r = extract_price_to_beat(market)
        self.assertEqual(r.status, "UNAVAILABLE")
        warnings = reject_non_authoritative_fallbacks(
            {"reference_price": 81000.0, "strike": 80000, "tradingReferencePx": 80500}
        )
        self.assertGreaterEqual(len(warnings), 2)

    def test_strike_and_trading_reference_do_not_authorize(self):
        market = {
            "slug": "cpc-btc-updown-15m-x",
            "assetPriceTerms": {
                "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                "horizon": "15m",
                "indexSymbol": "BRTI",
                "windowStart": "2026-10-17T19:00:00Z",
                "windowEnd": "2026-10-17T19:15:00Z",
                "priceToBeat": None,
                "strike": {"value": "80000", "currency": "USD"},
                "asset": {"symbol": "btc"},
            },
        }
        r = extract_price_to_beat(market, provenance_trusted=True)
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "price_to_beat_null")

    def test_valid_synthetic_metadata_unavailable_without_trusted_provenance(self):
        market = {
            "slug": "cpc-btc-updown-15m-2026-10-17-1900z",
            "assetPriceTerms": {
                "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                "horizon": "15m",
                "indexSymbol": "BRTI",
                "windowStart": "2026-10-17T19:00:00Z",
                "windowEnd": "2026-10-17T19:15:00Z",
                "priceToBeat": {"value": "81453.25", "currency": "USD"},
                "asset": {"symbol": "btc"},
            },
        }
        r = extract_price_to_beat(market)  # default provenance_trusted=False
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "metadata_source_unverified")

    def test_trusted_synthetic_available(self):
        market = {
            "slug": "cpc-btc-updown-15m-2026-10-17-1900z",
            "assetPriceTerms": {
                "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                "horizon": "15m",
                "indexSymbol": "BRTI",
                "windowStart": "2026-10-17T19:00:00Z",
                "windowEnd": "2026-10-17T19:15:00Z",
                "priceToBeat": {"value": "81453.25", "currency": "USD"},
                "asset": {"symbol": "btc"},
            },
        }
        r = extract_price_to_beat(market, provenance_trusted=True)
        self.assertEqual(r.status, "AVAILABLE")
        self.assertEqual(r.value, 81453.25)

    def test_us_panel_does_not_fill_from_international_midpoint(self):
        self.assertIn("US outcome quotes unavailable", self.src)
        self.assertIn("international book not used for US panel", self.src)


    def test_wrong_horizon_rejected(self):
        market = {
            "slug": "x",
            "assetPriceTerms": {
                "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                "horizon": "1h",
                "indexSymbol": "BRTI",
                "windowStart": "2026-10-17T19:00:00Z",
                "windowEnd": "2026-10-17T20:00:00Z",
                "priceToBeat": {"value": "81453.25", "currency": "USD"},
            },
        }
        r = extract_price_to_beat(market)
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "not_15m_horizon")

    def test_client_verification_flag_ignored(self):
        market = {"slug": "x", "provenance_verified": True, "source": "verified"}
        r = extract_price_to_beat(market)
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "missing_asset_price_terms")

    def test_brti_guard_default_fail_closed(self):
        market = {
            "slug": "x",
            "assetPriceTerms": {
                "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
                "horizon": "15m",
                "indexSymbol": "NOT_BRTI",
                "windowStart": "2026-10-17T19:00:00Z",
                "windowEnd": "2026-10-17T19:15:00Z",
                "priceToBeat": {"value": "81453.25", "currency": "USD"},
            },
        }
        r = extract_price_to_beat(market)
        self.assertEqual(r.status, "UNAVAILABLE")
        self.assertEqual(r.reason, "index_symbol_unverified_or_mismatch")

    def test_help_text_no_longer_equates_observation_to_target(self):
        self.assertNotIn(
            "Price to beat is the BTC reference price recorded for the contract.",
            self.src,
        )
        self.assertIn("assetPriceTerms.priceToBeat", self.src)


class TestFlaskRouteOptional(unittest.TestCase):
    def test_current_contract_route_without_db(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("Flask not installed — route test NOT RUN")


if __name__ == "__main__":
    unittest.main()
