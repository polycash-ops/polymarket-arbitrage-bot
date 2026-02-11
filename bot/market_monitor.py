"""
Real-time market monitor for exchanges and Polymarket
Tracks Bitcoin prices across multiple exchanges and detects temporal arbitrage opportunities
"""
import asyncio
import aiohttp
import websockets
import json
import time
from typing import Dict, List, Optional
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
        
    def add_callback(self, callback):
        """Add callback for price updates"""
        self.callbacks.append(callback)
        
    async def start(self):
        """Start monitoring all exchanges"""
        logger.info("🔍 Starting Market Monitor...")
        self.running = True
        self.session = aiohttp.ClientSession()
        
        # Start all exchange monitors concurrently
        tasks = [
            asyncio.create_task(self._monitor_binance()),
            asyncio.create_task(self._monitor_coinbase()),
            asyncio.create_task(self._monitor_kraken()),
            asyncio.create_task(self._monitor_polymarket()),
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
    async def stop(self):
        """Stop monitoring"""
        logger.info("🛑 Stopping Market Monitor...")
        self.running = False
        if self.session:
            await self.session.close()
            
    async def _monitor_binance(self):
        """Monitor Binance WebSocket for BTC prices"""
        uri = "wss://stream.binance.com:9443/ws/btcusdt@ticker"
        
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    logger.info("✅ Connected to Binance WebSocket")
                    
                    async for message in websocket:
                        if not self.running:
                            break
                            
                        data = json.loads(message)
                        
                        price_point = PricePoint(
                            exchange="binance",
                            price=float(data['c']),  # Last price
                            timestamp=time.time(),
                            volume=float(data['v']),  # Volume
                            bid=float(data['b']),     # Best bid
                            ask=float(data['a'])      # Best ask
                        )
                        
                        self.prices['binance'] = price_point
                        await self._notify_callbacks('binance', price_point)
                        
            except Exception as e:
                logger.error(f"❌ Binance WebSocket error: {e}")
                await asyncio.sleep(5)  # Reconnect after 5s
                
    async def _monitor_coinbase(self):
        """Monitor Coinbase WebSocket for BTC prices"""
        uri = "wss://ws-feed.pro.coinbase.com"
        
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    # Subscribe to BTC-USD ticker
                    subscribe_msg = {
                        "type": "subscribe",
                        "product_ids": ["BTC-USD"],
                        "channels": ["ticker"]
                    }
                    await websocket.send(json.dumps(subscribe_msg))
                    logger.info("✅ Connected to Coinbase WebSocket")
                    
                    async for message in websocket:
                        if not self.running:
                            break
                            
                        data = json.loads(message)
                        
                        if data.get('type') == 'ticker':
                            price_point = PricePoint(
                                exchange="coinbase",
                                price=float(data['price']),
                                timestamp=time.time(),
                                volume=float(data['volume_24h']),
                                bid=float(data['best_bid']),
                                ask=float(data['best_ask'])
                            )
                            
                            self.prices['coinbase'] = price_point
                            await self._notify_callbacks('coinbase', price_point)
                            
            except Exception as e:
                logger.error(f"❌ Coinbase WebSocket error: {e}")
                await asyncio.sleep(5)
                
    async def _monitor_kraken(self):
        """Monitor Kraken WebSocket for BTC prices"""
        uri = "wss://ws.kraken.com"
        
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    # Subscribe to BTC/USD ticker
                    subscribe_msg = {
                        "event": "subscribe",
                        "pair": ["XBT/USD"],
                        "subscription": {"name": "ticker"}
                    }
                    await websocket.send(json.dumps(subscribe_msg))
                    logger.info("✅ Connected to Kraken WebSocket")
                    
                    async for message in websocket:
                        if not self.running:
                            break
                            
                        data = json.loads(message)
                        
                        if isinstance(data, list) and len(data) >= 2:
                            ticker_data = data[1]
                            if 'c' in ticker_data:  # Last trade price
                                price_point = PricePoint(
                                    exchange="kraken",
                                    price=float(ticker_data['c'][0]),
                                    timestamp=time.time(),
                                    volume=float(ticker_data['v'][1]),  # 24h volume
                                    bid=float(ticker_data['b'][0]),      # Best bid
                                    ask=float(ticker_data['a'][0])       # Best ask
                                )
                                
                                self.prices['kraken'] = price_point
                                await self._notify_callbacks('kraken', price_point)
                                
            except Exception as e:
                logger.error(f"❌ Kraken WebSocket error: {e}")
                await asyncio.sleep(5)
                
    async def _monitor_polymarket(self):
        """Monitor Polymarket for Bitcoin prediction markets"""
        # This will monitor Bitcoin 15min markets on Polymarket
        # Using HTTP polling since Polymarket doesn't have public WebSocket
        
        while self.running:
            try:
                if not self.session:
                    continue
                    
                # Get Bitcoin markets from Polymarket API
                url = "https://gamma-api.polymarket.com/markets"
                params = {
                    "limit": 50,
                    "offset": 0,
                    "active": True,
                    "closed": False
                }
                
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Look for Bitcoin price prediction markets
                        bitcoin_markets = []
                        for market in data:
                            if 'bitcoin' in market.get('question', '').lower() or 'btc' in market.get('question', '').lower():
                                bitcoin_markets.append(market)
                                
                        if bitcoin_markets:
                            # Process the most relevant Bitcoin market
                            market = bitcoin_markets[0]
                            
                            # Extract price prediction from market data
                            outcomes = market.get('outcomes', [])
                            if outcomes:
                                yes_price = float(outcomes[0].get('price', 0))
                                
                                price_point = PricePoint(
                                    exchange="polymarket",
                                    price=yes_price,  # This is prediction probability, not BTC price
                                    timestamp=time.time(),
                                    volume=float(market.get('volume', 0))
                                )
                                
                                self.prices['polymarket'] = price_point
                                await self._notify_callbacks('polymarket', price_point)
                                
                await asyncio.sleep(2)  # Poll every 2 seconds
                
            except Exception as e:
                logger.error(f"❌ Polymarket polling error: {e}")
                await asyncio.sleep(5)
                
    async def _notify_callbacks(self, exchange: str, price_point: PricePoint):
        """Notify all callbacks about price updates"""
        for callback in self.callbacks:
            try:
                await callback(exchange, price_point)
            except Exception as e:
                logger.error(f"❌ Callback error: {e}")
                
    def get_latest_prices(self) -> Dict[str, PricePoint]:
        """Get latest prices from all exchanges"""
        return self.prices.copy()
        
    def get_price_spread(self) -> Dict[str, float]:
        """Calculate price spreads between exchanges"""
        spreads = {}
        exchanges = ['binance', 'coinbase', 'kraken']
        
        for i, ex1 in enumerate(exchanges):
            for ex2 in exchanges[i+1:]:
                if ex1 in self.prices and ex2 in self.prices:
                    price1 = self.prices[ex1].price
                    price2 = self.prices[ex2].price
                    spread = abs(price1 - price2) / min(price1, price2) * 100
                    spreads[f"{ex1}-{ex2}"] = spread
                    
        return spreads