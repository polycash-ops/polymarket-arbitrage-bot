import unittest
from datetime import datetime, timezone, timedelta

from polymarket_us_ptb import acquire_official_price_to_beat, current_btc_15m_slug, current_btc_15m_window


class OfficialPtbAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 12, 7, tzinfo=timezone.utc)
        self.slug, self.start, self.end = current_btc_15m_window(self.now)
        self.market = {
            "slug": self.slug,
            "active": True,
            "closed": False,
            "assetPriceTerms": {
                "asset": {"assetClass": "ASSET_CLASS_CRYPTO", "symbol": "btc"},
                "windowStart": self.start.isoformat(),
                "windowEnd": self.end.isoformat(),
                "priceToBeat": {"value": 67234.56, "currency": "USD"},
            },
        }

    def test_slug_is_current_15_minute_utc_boundary(self):
        self.assertEqual(self.slug, "btc-updown-15m-2026-10-18-1200z")
        self.assertEqual(current_btc_15m_slug(self.now), self.slug)

    def test_reads_explicit_official_us_price_to_beat(self):
        urls = []
        result = acquire_official_price_to_beat(self.now, fetch_json=lambda url: (urls.append(url) or {"market": self.market}))
        self.assertEqual(result["source"], "polymarket_us_official")
        self.assertEqual(result["contract_id"], self.slug)
        self.assertEqual(result["price_to_beat"], 67234.56)
        self.assertEqual(result["source_field"], "market.assetPriceTerms.priceToBeat")
        self.assertEqual(len(urls), 1)
        self.assertIn(self.slug, urls[0])

    def test_missing_or_invalid_target_fails_closed(self):
        for terms in (
            {**self.market["assetPriceTerms"], "priceToBeat": None},
            {**self.market["assetPriceTerms"], "priceToBeat": {"value": 0, "currency": "USD"}},
            {**self.market["assetPriceTerms"], "priceToBeat": {"value": 100, "currency": "EUR"}},
            {**self.market["assetPriceTerms"], "priceToBeat": {"value": "NaN", "currency": "USD"}},
        ):
            with self.subTest(terms=terms):
                market = {**self.market, "assetPriceTerms": terms}
                result = acquire_official_price_to_beat(self.now, fetch_json=lambda url, market=market: {"market": market})
                self.assertEqual(result["status"], "unavailable")
                self.assertIsNone(result["price_to_beat"])

    def test_rejects_wrong_contract_asset_or_lifecycle(self):
        variants = (
            {**self.market, "slug": "different"},
            {**self.market, "active": False},
            {**self.market, "closed": True},
            {**self.market, "assetPriceTerms": {**self.market["assetPriceTerms"], "asset": {"assetClass": "ASSET_CLASS_CRYPTO", "symbol": "eth"}}},
            {**self.market, "assetPriceTerms": {**self.market["assetPriceTerms"], "windowStart": (self.start - timedelta(minutes=15)).isoformat()}},
        )
        for market in variants:
            with self.subTest(market=market):
                result = acquire_official_price_to_beat(self.now, fetch_json=lambda url, market=market: {"market": market})
                self.assertEqual(result["status"], "unavailable")
                self.assertIsNone(result["price_to_beat"])

    def test_transport_error_fails_closed(self):
        result = acquire_official_price_to_beat(self.now, fetch_json=lambda url: (_ for _ in ()).throw(TimeoutError("test")))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("TimeoutError", result["reason"])


if __name__ == "__main__":
    unittest.main()
