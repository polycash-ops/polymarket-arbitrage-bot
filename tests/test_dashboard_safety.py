import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = (ROOT / "dashboard.py").read_text(encoding="utf-8")
PTB_ADAPTER = (ROOT / "polymarket_us_ptb.py").read_text(encoding="utf-8")


class DashboardSafetyTests(unittest.TestCase):
    def test_international_polymarket_quote_endpoints_are_not_used(self):
        self.assertNotIn("gamma-api.polymarket.com", DASHBOARD)
        self.assertNotIn("clob.polymarket.com", DASHBOARD)

    def test_official_us_market_field_is_the_only_ptb_producer(self):
        self.assertIn("acquire_official_price_to_beat()", DASHBOARD)
        self.assertIn("market.assetPriceTerms.priceToBeat", PTB_ADAPTER)
        self.assertIn("https://gateway.polymarket.us/v1/market/slug/{}", PTB_ADAPTER)
        self.assertIn("priceToBeat", PTB_ADAPTER)
        self.assertIn("Exchange reference (not PTB)", DASHBOARD)
        self.assertIn("NULL::double precision AS price_to_beat", DASHBOARD)

    def test_target_lifecycle_is_fail_closed(self):
        self.assertIn("function canonicalPtbValue", DASHBOARD)
        self.assertIn('payload.source!=="polymarket_us_official"', DASHBOARD)
        self.assertIn("payload.contract_id!==expectedContractId", DASHBOARD)
        self.assertIn("function expectedCurrentUsContractId", DASHBOARD)
        self.assertIn("function isCurrentLiveQuoteResponse", DASHBOARD)
        self.assertIn("updatePtbForContract(expectedCurrentUsContractId(),ptb)", DASHBOARD)
        self.assertIn("if(!isCurrentLiveQuoteResponse(requestId,liveQuoteRequestId))return", DASHBOARD)
        self.assertIn("clearPtb();", DASHBOARD)

    def test_research_and_live_trading_guards_remain(self):
        self.assertIn('"research_only": True, "live_trading_enabled": False', DASHBOARD)
        self.assertIn('@app.get("/health")', DASHBOARD)
        self.assertIn('return jsonify({"ok": True, "live_trading": False})', DASHBOARD)


if __name__ == "__main__":
    unittest.main()
