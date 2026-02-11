"""
Temporal Arbitrage Opportunity Detector
Detects when exchange prices move before Polymarket updates
Based on 0x8dxd's proven strategy
"""
import asyncio
import time
import statistics
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
import logging

from .market_monitor import PricePoint

logger = logging.getLogger(__name__)

@dataclass
class Opportunity:
    timestamp: float
    exchange_moved: str
    polymarket_delay: float  # Seconds
    price_difference: float  # Percentage
    confidence: float  # 0-1 score
    direction: str  # 'up' or 'down'
    recommended_action: str  # 'buy_yes', 'buy_no', 'wait'
    market_id: Optional[str] = None
    expected_profit: float = 0.0
    risk_level: str = 'medium'

@dataclass 
class PriceHistory:
    prices: deque = field(default_factory=lambda: deque(maxlen=60))  # Keep 60 data points
    timestamps: deque = field(default_factory=lambda: deque(maxlen=60))
    
    def add_price(self, price: float, timestamp: float):
        self.prices.append(price)
        self.timestamps.append(timestamp)
        
    def get_recent_trend(self, seconds: int = 30) -> str:
        """Get trend direction for last N seconds"""
        if len(self.prices) < 2:
            return 'unknown'
            
        cutoff_time = time.time() - seconds
        recent_prices = []
        
        for i, ts in enumerate(self.timestamps):
            if ts >= cutoff_time:
                recent_prices.append(self.prices[i])
                
        if len(recent_prices) < 2:
            return 'unknown'
            
        if recent_prices[-1] > recent_prices[0] * 1.001:  # >0.1% increase
            return 'up'
        elif recent_prices[-1] < recent_prices[0] * 0.999:  # >0.1% decrease
            return 'down'
        else:
            return 'flat'

class OpportunityDetector:
    def __init__(self, config: dict):
        self.config = config
        self.price_history: Dict[str, PriceHistory] = {}
        self.last_polymarket_update = 0
        self.opportunities = deque(maxlen=100)  # Keep last 100 opportunities
        self.callbacks = []
        
        # Thresholds from config
        self.min_price_diff = config.get('min_price_difference', 0.3)  # 0.3%
        self.min_confidence = config.get('min_confidence', 0.7)
        self.max_delay = config.get('max_delay_seconds', 15)  # 15 seconds max delay
        
    def add_callback(self, callback):
        """Add callback for new opportunities"""
        self.callbacks.append(callback)
        
    async def on_price_update(self, exchange: str, price_point: PricePoint):
        """Handle price updates from market monitor"""
        
        # Initialize price history if needed
        if exchange not in self.price_history:
            self.price_history[exchange] = PriceHistory()
            
        # Add to history
        self.price_history[exchange].add_price(price_point.price, price_point.timestamp)
        
        # Special handling for Polymarket
        if exchange == 'polymarket':
            self.last_polymarket_update = price_point.timestamp
            return
            
        # Check for temporal arbitrage opportunities
        await self._check_temporal_arbitrage(exchange, price_point)
        
    async def _check_temporal_arbitrage(self, moved_exchange: str, price_point: PricePoint):
        """Check if price movement creates temporal arbitrage opportunity"""
        
        # Get trend for the exchange that just moved
        trend = self.price_history[moved_exchange].get_recent_trend(30)
        
        if trend == 'unknown' or trend == 'flat':
            return
            
        # Calculate time since last Polymarket update
        polymarket_delay = time.time() - self.last_polymarket_update
        
        # Skip if Polymarket was updated too recently (no arbitrage opportunity)
        if polymarket_delay < 5:
            return
            
        # Skip if delay is too long (opportunity expired)
        if polymarket_delay > self.max_delay:
            return
            
        # Calculate price difference vs other exchanges
        price_differences = self._calculate_price_differences(moved_exchange)
        
        if not price_differences:
            return
            
        max_diff = max(price_differences.values())
        
        # Check if difference is significant enough
        if max_diff < self.min_price_diff:
            return
            
        # Calculate confidence score
        confidence = self._calculate_confidence(
            moved_exchange, trend, polymarket_delay, max_diff, price_differences
        )
        
        if confidence < self.min_confidence:
            return
            
        # Create opportunity
        opportunity = Opportunity(
            timestamp=time.time(),
            exchange_moved=moved_exchange,
            polymarket_delay=polymarket_delay,
            price_difference=max_diff,
            confidence=confidence,
            direction=trend,
            recommended_action=self._get_recommended_action(trend, confidence),
            expected_profit=self._estimate_profit(max_diff, confidence),
            risk_level=self._assess_risk(confidence, polymarket_delay)
        )
        
        # Log opportunity
        logger.info(
            f"🎯 OPPORTUNITY DETECTED: {moved_exchange} moved {trend} "
            f"{max_diff:.2f}%, Polymarket delay {polymarket_delay:.1f}s, "
            f"confidence {confidence:.2f}, action: {opportunity.recommended_action}"
        )
        
        # Store and notify
        self.opportunities.append(opportunity)
        await self._notify_callbacks(opportunity)
        
    def _calculate_price_differences(self, reference_exchange: str) -> Dict[str, float]:
        """Calculate price differences between reference exchange and others"""
        if reference_exchange not in self.price_history:
            return {}
            
        ref_prices = self.price_history[reference_exchange].prices
        if not ref_prices:
            return {}
            
        ref_price = ref_prices[-1]  # Latest price
        differences = {}
        
        # Compare with other exchanges
        for exchange, history in self.price_history.items():
            if exchange == reference_exchange or exchange == 'polymarket':
                continue
                
            if not history.prices:
                continue
                
            other_price = history.prices[-1]
            diff_pct = abs(ref_price - other_price) / other_price * 100
            differences[exchange] = diff_pct
            
        return differences
        
    def _calculate_confidence(self, moved_exchange: str, trend: str, delay: float, 
                            max_diff: float, price_differences: Dict[str, float]) -> float:
        """Calculate confidence score for the opportunity"""
        confidence = 0.0
        
        # Base confidence from price difference (0-0.4)
        confidence += min(max_diff / 2.0, 0.4)
        
        # Bonus for delay timing (0-0.3)
        ideal_delay = 8  # 8 seconds is ideal
        delay_score = max(0, 1 - abs(delay - ideal_delay) / ideal_delay)
        confidence += delay_score * 0.3
        
        # Bonus for trend strength (0-0.2)
        recent_prices = self.price_history[moved_exchange].prices
        if len(recent_prices) >= 3:
            trend_strength = abs(recent_prices[-1] - recent_prices[-3]) / recent_prices[-3]
            confidence += min(trend_strength * 100, 0.2)
            
        # Bonus for consistent differences across exchanges (0-0.1)
        if price_differences:
            consistency = 1 - (statistics.stdev(price_differences.values()) / max(price_differences.values()))
            confidence += consistency * 0.1
            
        return min(confidence, 1.0)
        
    def _get_recommended_action(self, trend: str, confidence: float) -> str:
        """Get recommended trading action"""
        if confidence < 0.7:
            return 'wait'
            
        if trend == 'up':
            return 'buy_yes'  # Buy YES tokens (price will go up)
        elif trend == 'down':
            return 'buy_no'   # Buy NO tokens (price will go down)
        else:
            return 'wait'
            
    def _estimate_profit(self, price_diff: float, confidence: float) -> float:
        """Estimate expected profit percentage"""
        # Conservative estimate: capture 30% of price difference, weighted by confidence
        return price_diff * 0.3 * confidence
        
    def _assess_risk(self, confidence: float, delay: float) -> str:
        """Assess risk level of the opportunity"""
        if confidence > 0.8 and delay < 10:
            return 'low'
        elif confidence > 0.6 and delay < 12:
            return 'medium'
        else:
            return 'high'
            
    async def _notify_callbacks(self, opportunity: Opportunity):
        """Notify all callbacks about new opportunity"""
        for callback in self.callbacks:
            try:
                await callback(opportunity)
            except Exception as e:
                logger.error(f"❌ Opportunity callback error: {e}")
                
    def get_recent_opportunities(self, minutes: int = 60) -> List[Opportunity]:
        """Get opportunities from last N minutes"""
        cutoff_time = time.time() - (minutes * 60)
        return [opp for opp in self.opportunities if opp.timestamp >= cutoff_time]
        
    def get_success_rate(self) -> float:
        """Calculate success rate of recent opportunities"""
        recent_opps = self.get_recent_opportunities(240)  # 4 hours
        if not recent_opps:
            return 0.0
            
        # This would need trade results to calculate actual success rate
        # For now, return estimated success rate based on confidence
        avg_confidence = sum(opp.confidence for opp in recent_opps) / len(recent_opps)
        return avg_confidence * 0.85  # Conservative estimate