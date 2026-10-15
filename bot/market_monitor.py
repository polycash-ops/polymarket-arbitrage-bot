"""
Real-time market monitor for exchanges and Polymarket.
Tracks BTC prices across exchanges and reads Polymarket prediction-market quotes.
"""
import asyncio
import aiohttp
import websockets
import json
import time
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class PricePoint:
    exchange: str
    price: float
    timestamp: float
    volume: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    market_id: Optional[str] = None
    question: Optional[str] = None
    end_time: Optional[float] = None
    yes_outcome_index: int = 0


class MarketMonitor:
    def __init__(self, config: dict):
        self.config = config
        self.prices: Dict[str, PricePoint] = {}
        self.callbacks = []
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.polymarket_market_key: Optional[str] = None

    def add_callback(self, callback):
        """Add callback for price updates."""
        self.callbacks.append(callback)

    async def start(self):
        """Start monitoring all exchanges."""
        logger.info("🔍 Starting Market Monitor...")
        self.running = True
        self.session = aiohttp.ClientSession()
        tasks = [
            asyncio.create_task(self._monitor_binance()),
            asyncio.create_task(self._monitor_coinbase()),
            asyncio.create_task(self._monitor_kraken()),
            asyncio.create_task(self._monitor_polymarket()),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self):
        """Stop monitoring."""
        logger.info("🛑 Stopping Market Monitor...")
        self.running = False
        if self.session:
            await self.session.close()

    async def _monitor_binance(self):
        """Poll Binance US public BTC/USD endpoints for US-hosted workers."""
        url = "https://api.binance.us/api/v3/ticker/24hr"
        book_url = "https://api.binance.us/api/v3/ticker/bookTicker"
        while self.running:
            try:
                if not self.session:
                    await asyncio.sleep(1)
                    continue
                async with self.session.get(url, params={"symbol": "BTCUSD"}) as response:
                    response.raise_for_status()
                    data = await response.json()
                bid = ask = None
                async with self.session.get(book_url, params={"symbol": "BTCUSD"}) as response:
                    if response.status == 200:
                        book = await response.json()
                        bid, ask = float(book["bidPrice"]), float(book["askPrice"])
                point = PricePoint(
                    exchange="binance", price=float(data["lastPrice"]),
                    timestamp=time.time(), volume=float(data.get("volume") or 0),
                    bid=bid, ask=ask
                )
                self.prices["binance"] = point
                await self._notify_callbacks("binance", point)
                await asyncio.sleep(2)
            except Exception as exc:
                logger.warning("Binance US REST polling error: %s", exc)
                await asyncio.sleep(5)

    async def _monitor_coinbase(self):
        """Poll Coinbase's public Exchange REST ticker."""
        url = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
        while self.running:
            try:
                if not self.session:
                    await asyncio.sleep(1)
                    continue
                async with self.session.get(url, headers={"User-Agent": "paper-arbitrage-research/1.0"}) as response:
                    response.raise_for_status()
                    data = await response.json()
                point = PricePoint(
                    exchange="coinbase", price=float(data["price"]),
                    timestamp=time.time(), volume=float(data.get("volume") or 0),
                    bid=float(data["bid"]), ask=float(data["ask"])
                )
                self.prices["coinbase"] = point
                await self._notify_callbacks("coinbase", point)
                await asyncio.sleep(2)
            except Exception as exc:
                logger.warning("Coinbase REST polling error: %s", exc)
                await asyncio.sleep(5)

    async def _monitor_kraken(self):
        """Monitor Kraken WebSocket for BTC prices."""
        uri = "wss://ws.kraken.com"
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    await websocket.send(json.dumps({
                        "event": "subscribe", "pair": ["XBT/USD"],
                        "subscription": {"name": "ticker"}
                    }))
                    logger.info("✅ Connected to Kraken WebSocket")
                    async for message in websocket:
                        if not self.running:
                            break
                        data = json.loads(message)
                        if isinstance(data, list) and len(data) >= 2:
                            ticker = data[1]
                            if isinstance(ticker, dict) and "c" in ticker:
                                point = PricePoint(
                                    exchange="kraken", price=float(ticker["c"][0]),
                                    timestamp=time.time(), volume=float(ticker["v"][1]),
                                    bid=float(ticker["b"][0]), ask=float(ticker["a"][0])
                                )
                                self.prices["kraken"] = point
                                await self._notify_callbacks("kraken", point)
            except Exception as exc:
                logger.error("❌ Kraken WebSocket error: %s", exc)
                await asyncio.sleep(5)

    @staticmethod
    def _as_list(value):
        """Gamma may return array fields as JSON-encoded strings."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return []
        return value if isinstance(value, list) else []

    async def _monitor_polymarket(self):
        """Poll the active 15-minute BTC Up/Down contract and publish quote snapshots."""
        url = "https://gamma-api.polymarket.com/markets"
        while self.running:
            try:
                if not self.session:
                    await asyncio.sleep(1)
                    continue
                now = time.time()
                now_dt = datetime.fromtimestamp(now, timezone.utc)
                window_minute = (now_dt.minute // 15) * 15
                window_start = now_dt.replace(minute=window_minute, second=0, microsecond=0)
                slug_starts = [window_start, window_start + timedelta(minutes=15)]
                data = []
                # Query the known 15-minute BTC contract slug directly first; Gamma's
                # first page of active markets often omits these short-window contracts.
                for start_at in slug_starts:
                    expected_slug = f"cpc-btc-updown-15m-{start_at:%Y-%m-%d}-{start_at:%H%M}z"
                    async with self.session.get(url, params={"slug": expected_slug}) as response:
                        if response.status == 200:
                            result = await response.json()
                            if isinstance(result, list):
                                # Some API responses ignore unknown query filters; verify
                                # the returned slug locally before trusting the result.
                                data.extend(
                                    market for market in result
                                    if isinstance(market, dict)
                                    and str(market.get("slug") or "") == expected_slug
                                )
                if not data:
                    async with self.session.get(url, params={
                        "limit": 1000, "offset": 0, "active": "true", "closed": "false"
                    }) as response:
                        if response.status != 200:
                            logger.warning("Polymarket Gamma returned HTTP %s", response.status)
                        else:
                            result = await response.json()
                            data = result if isinstance(result, list) else []
                candidates = []
                for market in data if isinstance(data, list) else []:
                    if not isinstance(market, dict):
                        continue
                    question = str(market.get("question") or "")
                    slug = str(market.get("slug") or "")
                    q = question.lower()
                    s = slug.lower()
                    # Keep this strategy tied to the intended short-dated BTC Up/Down contract.
                    is_15m = ("15m" in s and ("btc" in s or "bitcoin" in s)) or (
                        ("up or down" in q or ("up" in q and "down" in q))
                        and ("bitcoin" in q or "btc" in q)
                        and ("15 minute" in q or "15m" in q)
                    )
                    if not is_15m:
                        continue
                    raw_end = market.get("endDate") or market.get("endDateIso") or market.get("end_date")
                    end_time = None
                    if raw_end:
                        try:
                            end_time = datetime.fromisoformat(str(raw_end).replace("Z", "+00:00")).timestamp()
                        except (TypeError, ValueError):
                            pass
                    if end_time is not None and end_time <= now:
                        continue
                    outcomes = self._as_list(market.get("outcomes"))
                    prices = self._as_list(market.get("outcomePrices"))
                    if not prices or len(prices) < 2:
                        continue
                    try:
                        first_price = float(prices[0])
                        second_price = float(prices[1])
                    except (TypeError, ValueError):
                        continue
                    if not (0 <= first_price <= 1 and 0 <= second_price <= 1):
                        continue
                    # Normalize the market to an Up-probability quote, regardless
                    # of the order in Gamma's outcomes array.
                    first_name = str(outcomes[0]).lower() if outcomes else "up"
                    second_name = str(outcomes[1]).lower() if len(outcomes) > 1 else "down"
                    if "down" in first_name and "up" in second_name:
                        up_price = second_price
                        outcome_order = "down_first"
                    else:
                        up_price = first_price
                        outcome_order = "up_first"
                    candidates.append((end_time or float("inf"), market, up_price, outcomes, outcome_order))
                if candidates:
                    candidates.sort(key=lambda item: item[0])
                    end_time, market, up_price, outcomes, outcome_order = candidates[0]
                    slug = str(market.get("slug") or market.get("id") or "")
                    question = str(market.get("question") or "BTC Up or Down 15m")
                    try:
                        volume = float(market.get("volume") or 0)
                    except (TypeError, ValueError):
                        volume = 0.0
                    bid = ask = None
                    try:
                        raw_bid = float(market["bestBid"]) if market.get("bestBid") is not None else None
                        raw_ask = float(market["bestAsk"]) if market.get("bestAsk") is not None else None
                        if outcome_order == "down_first":
                            bid = 1.0 - raw_ask if raw_ask is not None else None
                            ask = 1.0 - raw_bid if raw_bid is not None else None
                        else:
                            bid, ask = raw_bid, raw_ask
                    except (TypeError, ValueError):
                        bid = ask = None
                    point = PricePoint(
                        exchange="polymarket", price=up_price, timestamp=now,
                        volume=volume, bid=bid, ask=ask, market_id=slug,
                        question=question, end_time=None if end_time == float("inf") else end_time
                    )
                    self.prices["polymarket"] = point
                    self.polymarket_market_key = slug
                    # Publish every poll: the detector needs to distinguish a fresh poll
                    # from a probability that has remained unchanged.
                    await self._notify_callbacks("polymarket", point)
                else:
                    logger.warning("No eligible active BTC 15-minute Up/Down market found")
                await asyncio.sleep(2)
            except Exception as exc:
                logger.error("Polymarket polling error: %s", exc)
                await asyncio.sleep(5)

    async def _notify_callbacks(self, exchange: str, price_point: PricePoint):
        """Notify all price-update callbacks."""
        for callback in self.callbacks:
            try:
                await callback(exchange, price_point)
            except Exception as exc:
                logger.error("❌ Callback error: %s", exc)

    def get_latest_prices(self) -> Dict[str, PricePoint]:
        """Get latest prices from all exchanges."""
        return self.prices.copy()

    def get_price_spread(self) -> Dict[str, float]:
        """Calculate price spreads between supported crypto exchanges."""
        spreads = {}
        exchanges = ["binance", "coinbase", "kraken"]
        for i, ex1 in enumerate(exchanges):
            for ex2 in exchanges[i + 1:]:
                if ex1 in self.prices and ex2 in self.prices:
                    price1 = self.prices[ex1].price
                    price2 = self.prices[ex2].price
                    if min(price1, price2) > 0:
                        spreads[f"{ex1}-{ex2}"] = abs(price1 - price2) / min(price1, price2) * 100
        return spreads
