"""Binance BTCUSDT 15-minute window-open benchmark for Oracle paper direction.

This is a direction-only research reference. It is not official Polymarket PTB,
does not establish contract identity, and cannot support contract fill/P&L claims.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SYMBOL = "BTCUSDT"
INTERVAL = "15m"
CANDLE_MS = 15 * 60 * 1000
BASE_URL = "https://api.binance.com/api/v3/klines"


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def research_window(now: datetime) -> tuple[datetime, datetime]:
    """Return an explicitly UTC-aligned research window, not a contract ID."""
    now = as_utc(now)
    epoch_ms = int(now.timestamp() * 1000)
    start_ms = epoch_ms // CANDLE_MS * CANDLE_MS
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    return start, start + timedelta(minutes=15)


def _get_json(url: str, timeout: float = 5.0) -> Any:
    request = Request(url, headers={"User-Agent": "signal-oracle-paper-research/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        import json
        return json.loads(response.read().decode("utf-8"))


def parse_kline(payload: Any, window_start: datetime, *, acquired_at: datetime | None = None,
                require_final: bool = False) -> dict[str, Any]:
    """Validate Binance Spot kline shape and exact open-time alignment."""
    start = as_utc(window_start)
    acquired = as_utc(acquired_at or datetime.now(timezone.utc))
    expected_ms = int(start.timestamp() * 1000)
    if expected_ms % CANDLE_MS:
        raise ValueError("window start is not an exact UTC 15-minute boundary")
    if not isinstance(payload, list) or len(payload) < 1:
        raise ValueError("Binance kline response is empty")
    row = payload[0]
    if not isinstance(row, (list, tuple)) or len(row) < 7:
        raise ValueError("Binance kline has an invalid schema")
    try:
        open_ms = int(row[0])
        open_price = float(row[1])
        close_price = float(row[4])
        close_ms = int(row[6])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Binance kline timestamps or prices are invalid") from exc
    if open_ms != expected_ms:
        raise ValueError("Binance candle open timestamp does not exactly match window start")
    if not math.isfinite(open_price) or open_price <= 0:
        raise ValueError("Binance candle open price must be finite and positive")
    if not math.isfinite(close_price) or close_price <= 0:
        raise ValueError("Binance candle close price must be finite and positive")
    expected_close_ms = expected_ms + CANDLE_MS - 1
    if close_ms != expected_close_ms:
        raise ValueError("Binance candle close timestamp does not match the requested 15-minute interval")
    finalized = int(acquired.timestamp() * 1000) > close_ms
    if require_final and not finalized:
        raise ValueError("Binance candle is not finalized")
    return {
        "benchmark_name": "Oracle paper PTB — Binance",
        "qualifier": "Binance window-open benchmark; not official Polymarket PTB.",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "quote_currency": "USDT",
        "window_start": start.isoformat(),
        "window_end": (start + timedelta(minutes=15)).isoformat(),
        "benchmark_price": open_price,
        "benchmark_source_timestamp": datetime.fromtimestamp(open_ms / 1000, timezone.utc).isoformat(),
        "acquired_at": acquired.isoformat(),
        "close_price": close_price,
        "candle_close_source_timestamp": datetime.fromtimestamp(close_ms / 1000, timezone.utc).isoformat(),
        "finalized": finalized,
        "outcome": ("UP" if close_price > open_price else "DOWN" if close_price < open_price else "TIE") if finalized else "PENDING",
    }


def fetch_window_candle(window_start: datetime, *, now: datetime | None = None,
                        fetch_json: Callable[[str], Any] | None = None,
                        retry_attempts: int = 3, retry_interval: float = 2.0,
                        sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Fetch only the exact UTC candle; bounded retry never falls back to ticker."""
    start = as_utc(window_start)
    start_ms = int(start.timestamp() * 1000)
    if start_ms % CANDLE_MS:
        raise ValueError("window start is not an exact UTC 15-minute boundary")
    url = BASE_URL + "?" + urlencode({
        "symbol": SYMBOL, "interval": INTERVAL, "startTime": start_ms,
        "endTime": start_ms + CANDLE_MS - 1, "limit": 1,
    })
    fetch = fetch_json or (lambda target: _get_json(target))
    last_error = None
    for attempt in range(max(0, int(retry_attempts)) + 1):
        try:
            data = fetch(url)
            result = parse_kline(data, start, acquired_at=now or datetime.now(timezone.utc))
            return result
        except Exception as exc:
            last_error = exc
            if attempt >= max(0, int(retry_attempts)):
                break
            sleep_fn(max(0.0, float(retry_interval)))
    raise ValueError("Exact Binance BTCUSDT 15m candle unavailable after bounded retries: " + str(last_error))


def score_direction(prediction: str, candle: dict[str, Any]) -> dict[str, Any]:
    action = str(prediction).upper()
    outcome = str(candle.get("outcome", "PENDING")).upper()
    if action not in {"UP", "DOWN"}:
        return {"status": "excluded", "reason": "NO TRADE is not a directional prediction", "correct": None}
    if outcome == "PENDING" or candle.get("finalized") is not True:
        return {"status": "pending", "reason": "Binance candle is not finalized", "correct": None}
    if outcome == "TIE":
        return {"status": "tie", "reason": "final candle close equals its open", "correct": None}
    if outcome not in {"UP", "DOWN"}:
        return {"status": "pending", "reason": "valid finalized candle outcome unavailable", "correct": None}
    return {"status": "resolved", "outcome": outcome, "correct": action == outcome,
            "accuracy_label": "Binance direction accuracy"}

def fetch_current_quote(*, now: datetime | None = None,
                        fetch_json: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Fetch an informational current BTCUSDT ticker; never use it as the PTB."""
    acquired = as_utc(now or datetime.now(timezone.utc))
    url = BASE_URL.replace("/klines", "/ticker/price") + "?" + urlencode({"symbol": SYMBOL})
    data = (fetch_json or (lambda target: _get_json(target)))(url)
    if not isinstance(data, dict) or data.get("symbol") != SYMBOL:
        raise ValueError("Binance current ticker symbol is not BTCUSDT")
    try:
        price = float(data.get("price"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Binance current ticker price is invalid") from exc
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Binance current ticker price must be finite and positive")
    return {"symbol": SYMBOL, "price": price, "quote_timestamp": acquired.isoformat(),
            "quote_timestamp_type": "local acquisition time; Binance ticker response has no source timestamp"}
