import unittest
from datetime import datetime, timezone

from bot.signal_oracle_binance import (
    CANDLE_MS, fetch_current_quote, fetch_window_candle, parse_kline, research_window, score_direction,
)


class BinancePaperPtbTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        self.open_ms = int(self.start.timestamp() * 1000)
        self.close_ms = self.open_ms + CANDLE_MS - 1
        self.row = [self.open_ms, "80000.0", "80200.0", "79900.0", "80100.0",
                    "12.3", self.close_ms, "x", 4, "x", "x", "0"]

    def test_utc_window_floor_and_ms_timestamp(self):
        start, end = research_window(datetime(2026, 10, 18, 12, 14, 59, 999000, timezone.utc))
        self.assertEqual(start, self.start)
        self.assertEqual((end - start).total_seconds(), 900)
        candle = parse_kline([self.row], self.start,
            acquired_at=datetime(2026, 10, 18, 12, 15, 1, tzinfo=timezone.utc))
        self.assertEqual(candle["benchmark_source_timestamp"], self.start.isoformat())
        self.assertEqual(candle["quote_currency"], "USDT")
        self.assertEqual(candle["outcome"], "UP")

    def test_wrong_open_timestamp_rejected(self):
        row = list(self.row)
        row[0] += CANDLE_MS
        with self.assertRaisesRegex(ValueError, "exactly match"):
            parse_kline([row], self.start, acquired_at=datetime(2026, 10, 18, 12, 15, tzinfo=timezone.utc))

    def test_unfinalized_candle_is_not_scored(self):
        candle = parse_kline([self.row], self.start,
            acquired_at=datetime(2026, 10, 18, 12, 14, 59, tzinfo=timezone.utc))
        self.assertFalse(candle["finalized"])
        self.assertEqual(score_direction("UP", candle)["status"], "pending")

    def test_equal_open_close_is_tie(self):
        row = list(self.row)
        row[4] = row[1]
        candle = parse_kline([row], self.start,
            acquired_at=datetime(2026, 10, 18, 12, 16, tzinfo=timezone.utc), require_final=True)
        self.assertEqual(candle["outcome"], "TIE")
        self.assertEqual(score_direction("UP", candle)["status"], "tie")

    def test_down_outcome_and_incorrect_prediction(self):
        row = list(self.row)
        row[4] = "79900.0"
        candle = parse_kline([row], self.start,
            acquired_at=datetime(2026, 10, 18, 12, 16, tzinfo=timezone.utc), require_final=True)
        self.assertEqual(candle["outcome"], "DOWN")
        self.assertFalse(score_direction("UP", candle)["correct"])
        self.assertTrue(score_direction("DOWN", candle)["correct"])

    def test_invalid_open_price_rejected(self):
        row = list(self.row)
        row[1] = "NaN"
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            parse_kline([row], self.start,
                acquired_at=datetime(2026, 10, 18, 12, 16, tzinfo=timezone.utc))

    def test_current_quote_is_separate_and_symbol_checked(self):
        quote = fetch_current_quote(now=datetime(2026, 10, 18, 12, 7, tzinfo=timezone.utc),
            fetch_json=lambda url: {"symbol": "BTCUSDT", "price": "80321.5"})
        self.assertEqual(quote["price"], 80321.5)
        self.assertEqual(quote["quote_timestamp"], "2026-10-18T12:07:00+00:00")
        with self.assertRaisesRegex(ValueError, "symbol"):
            fetch_current_quote(fetch_json=lambda url: {"symbol": "BTCUSD", "price": "80321.5"})

    def test_no_trade_is_excluded(self):
        candle = parse_kline([self.row], self.start,
            acquired_at=datetime(2026, 10, 18, 12, 16, tzinfo=timezone.utc), require_final=True)
        self.assertEqual(score_direction("NO TRADE", candle)["status"], "excluded")

    def test_fetch_uses_exact_symbol_interval_and_window(self):
        urls = []
        result = fetch_window_candle(self.start, now=datetime(2026, 10, 18, 12, 16, tzinfo=timezone.utc),
            fetch_json=lambda url: (urls.append(url) or [self.row]), retry_attempts=0)
        self.assertIn("symbol=BTCUSDT", urls[0])
        self.assertIn("interval=15m", urls[0])
        self.assertIn("startTime=" + str(self.open_ms), urls[0])
        self.assertEqual(result["benchmark_price"], 80000.0)
        self.assertEqual(result["qualifier"], "Binance window-open benchmark; not official Polymarket PTB.")

    def test_missing_candle_uses_bounded_retry_without_ticker_fallback(self):
        calls = []
        def fetch(_url):
            calls.append(1)
            if len(calls) == 1:
                return []
            return [self.row]
        result = fetch_window_candle(self.start, now=datetime(2026, 10, 18, 12, 16, tzinfo=timezone.utc),
            fetch_json=fetch, retry_attempts=1, sleep_fn=lambda _: None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["benchmark_price"], 80000.0)


if __name__ == "__main__":
    unittest.main()
