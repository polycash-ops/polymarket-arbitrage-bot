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
        """Poll Gamma for active BTC/Bitcoin prediction-market probabilities."""
        url = "https://gamma-api.polymarket.com/markets"
        params = {"limit": 50, "offset": 0, "active": "true", "closed": "false"}
        while self.running:
            try:
                if not self.session:
                    await asyncio.sleep(1)
                    continue
                async with self.session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.warning("Polymarket Gamma returned HTTP %s", response.status)
                    else:
                        data = await response.json()
                        bitcoin_markets = [
                            market for market in data
                            if isinstance(market, dict)
                            and any(term in str(market.get("question", "")).lower()
                                    for term in ("bitcoin", "btc"))
                        ]
                        if bitcoin_markets:
                            market = bitcoin_markets[0]
                            outcomes = self._as_list(market.get("outcomes"))
                            prices = self._as_list(market.get("outcomePrices"))
                            yes_price = None

                            # Gamma's usual schema has outcome names and a parallel
                            # outcomePrices array, not a price property on each outcome.
                            if outcomes and isinstance(outcomes[0], dict):
                                raw_price = outcomes[0].get("price")
                                if raw_price is not None:
                                    yes_price = float(raw_price)
                            elif prices:
                                yes_price = float(prices[0])

                            if yes_price is not None and 0 <= yes_price <= 1:
                                try:
                                    volume = float(market.get("volume") or 0)
                                except (TypeError, ValueError):
                                    volume = 0.0
                                market_key = str(market.get("slug") or market.get("id") or "")
                                previous = self.prices.get("polymarket")
                                changed = (
                                    previous is None
                                    or abs(previous.price - yes_price) > 1e-6
                                    or market_key != self.polymarket_market_key
                                )
                                if changed:
                                    point = PricePoint(
                                        exchange="polymarket", price=yes_price,
                                        timestamp=time.time(), volume=volume
                                    )
                                    self.prices["polymarket"] = point
                                    self.polymarket_market_key = market_key
                                    await self._notify_callbacks("polymarket", point)
                            else:
                                logger.warning(
                                    "Could not parse Polymarket probability for market %s",
                                    market.get("slug") or market.get("id") or "unknown"
                                )
                await asyncio.sleep(2)
            except Exception as exc:
                logger.error("❌ Polymarket polling error: %s", exc)
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
