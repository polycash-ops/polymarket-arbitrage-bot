"""
Temporal arbitrage detector for the forked paper-trading strategy.
A signal requires a BTC move confirmed across exchange feeds while the selected
15-minute Polymarket Up/Down probability has not yet followed that move.
"""
import asyncio
import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .market_monitor import PricePoint

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    timestamp: float
    exchange_moved: str
    polymarket_delay: float
    price_difference: float
    confidence: float
    direction: str
    recommended_action: str
    market_id: Optional[str] = None
    expected_profit: float = 0.0
    risk_level: str = "medium"
    market_question: Optional[str] = None
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    market_end_time: Optional[float] = None
    estimated_edge_probability: float = 0.0
    yes_outcome_index: int = 0


@dataclass
class PriceHistory:
    prices: deque = field(default_factory=lambda: deque(maxlen=300))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=300))

    def add_price(self, price: float, timestamp: float):
        self.prices.append(float(price))
        self.timestamps.append(float(timestamp))

    def get_change_pct(self, seconds: int = 30) -> Optional[float]:
        if len(self.prices) < 2:
            return None
        cutoff = time.time() - seconds
        recent = [(p, ts) for p, ts in zip(self.prices, self.timestamps) if ts >= cutoff]
        if len(recent) < 2 or recent[0][0] <= 0:
            return None
        return (recent[-1][0] - recent[0][0]) / recent[0][0] * 100

    def get_probability_change(self, seconds: int = 10) -> Optional[float]:
        if len(self.prices) < 2:
            return None
        cutoff = time.time() - seconds
        recent = [(p, ts) for p, ts in zip(self.prices, self.timestamps) if ts >= cutoff]
        if len(recent) < 2:
            return 0.0
        return recent[-1][0] - recent[0][0]


class OpportunityDetector:
    def __init__(self, config: dict):
        self.config = config
        self.price_history: Dict[str, PriceHistory] = {}
        self.last_polymarket_change = 0.0
        self.last_polymarket_price: Optional[float] = None
        self.last_market_id: Optional[str] = None
        self._latest_market_point: Optional[PricePoint] = None
        self.signaled_markets = set()
        self.opportunities = deque(maxlen=100)
        self.callbacks = []
        self.min_price_diff = float(config.get("min_price_difference", 0.03))
        self.min_confidence = float(config.get("min_confidence", 0.7))
        self.max_delay = float(config.get("max_delay_seconds", 15))
        self.min_probability_lag = float(config.get("min_probability_lag", 0.01))
        self.max_probability_followthrough = float(config.get("max_probability_followthrough", 0.01))
        self.min_consensus_exchanges = int(config.get("min_consensus_exchanges", 2))

    def add_callback(self, callback):
        self.callbacks.append(callback)

    async def on_price_update(self, exchange: str, price_point: PricePoint):
        history = self.price_history.setdefault(exchange, PriceHistory())
        history.add_price(price_point.price, price_point.timestamp)

        if exchange == "polymarket":
            self._latest_market_point = price_point
            market_changed = price_point.market_id != self.last_market_id
            price_changed = (
                self.last_polymarket_price is None
                or abs(price_point.price - self.last_polymarket_price) >= 0.005
            )
            if market_changed or price_changed:
                self.last_polymarket_change = price_point.timestamp
                self.last_polymarket_price = price_point.price
                self.last_market_id = price_point.market_id
            return

        await self._check_temporal_arbitrage(exchange, price_point)

    def _consensus_move(self) -> tuple[Optional[float], List[str]]:
        moves = {}
        for exchange in ("binance", "coinbase", "kraken"):
            history = self.price_history.get(exchange)
            if not history:
                continue
            change = history.get_change_pct(30)
            if change is not None:
                moves[exchange] = change
        if len(moves) < self.min_consensus_exchanges:
            return None, []
        values = list(moves.values())
        # Require a consistent sign across feeds; a single bad/outlier feed cannot trigger a trade.
        positive = sum(value > 0 for value in values)
        negative = sum(value < 0 for value in values)
        if positive >= self.min_consensus_exchanges and positive > negative:
            agreed = [value for value in values if value > 0]
        elif negative >= self.min_consensus_exchanges and negative > positive:
            agreed = [value for value in values if value < 0]
        else:
            return None, []
        return statistics.median(agreed), [name for name, value in moves.items() if value in agreed]

    async def _check_temporal_arbitrage(self, moved_exchange: str, price_point: PricePoint):
        market_history = self.price_history.get("polymarket")
        if not market_history:
            return
        current_market = getattr(self, "_latest_market_point", None)
        # The callback carries a new quote every poll; preserve the last complete market metadata.
        # Set by on_price_update below when Polymarket snapshots arrive.
        if current_market is None:
            return
        if not current_market.market_id:
            logger.info("Opportunity skipped: selected Polymarket market has no ID")
            return
        if current_market.market_id in self.signaled_markets:
            return
        if current_market.end_time is not None and current_market.end_time <= time.time() + 5:
            logger.info("Opportunity skipped: contract is at expiry")
            return

        delay = time.time() - self.last_polymarket_change
        if delay < 5 or delay > self.max_delay:
            return

        consensus_change, agreeing_exchanges = self._consensus_move()
        if consensus_change is None or abs(consensus_change) < self.min_price_diff:
            return
        direction = "up" if consensus_change > 0 else "down"

        quote_change = market_history.get_probability_change(10)
        if quote_change is None:
            return
        # YES is the first (Up) outcome for the selected BTC Up/Down contract.
        # If the probability has already followed the BTC move, there is no lag to trade.
        if direction == "up" and quote_change > self.max_probability_followthrough:
            logger.info("Opportunity skipped: Polymarket Up probability already followed BTC")
            return
        if direction == "down" and quote_change < -self.max_probability_followthrough:
            logger.info("Opportunity skipped: Polymarket Up probability already followed BTC")
            return

        yes_bid = current_market.bid
        yes_ask = current_market.ask
        if yes_bid is None or yes_ask is None or not (0 < yes_bid <= yes_ask < 1):
            logger.info("Opportunity skipped: Polymarket bid/ask unavailable or invalid")
            return

        # Estimate a conservative, configurable probability edge for paper evaluation only.
        edge = min(0.05, max(self.min_probability_lag, abs(consensus_change) * 0.5 / 100))
        confidence = self._calculate_confidence(abs(consensus_change), delay, quote_change, len(agreeing_exchanges))
        if confidence < self.min_confidence:
            logger.info(
                "Opportunity rejected: confidence %.3f below %.3f",
                confidence, self.min_confidence
            )
            return

        opportunity = Opportunity(
            timestamp=time.time(),
            exchange_moved=",".join(agreeing_exchanges),
            polymarket_delay=delay,
            price_difference=abs(consensus_change),
            confidence=confidence,
            direction=direction,
            recommended_action="buy_yes" if direction == "up" else "buy_no",
            market_id=current_market.market_id,
            # No dollar-profit claim until this edge is validated against settled outcomes.\n            expected_profit=0.0,
            risk_level=self._assess_risk(confidence, delay),
            market_question=current_market.question,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            market_end_time=current_market.end_time,
            estimated_edge_probability=edge,
            yes_outcome_index=current_market.yes_outcome_index,
        )
        logger.info(
            "OPPORTUNITY DETECTED market=%s direction=%s btc_move=%.4f%% "
            "quote_lag=%.4f probability_points delay=%.1fs confidence=%.3f action=%s",
            opportunity.market_id, direction, abs(consensus_change), quote_change,
            delay, confidence, opportunity.recommended_action
        )
        self.opportunities.append(opportunity)
        self.signaled_markets.add(current_market.market_id)
        await self._notify_callbacks(opportunity)

    def _calculate_confidence(self, btc_move_pct: float, delay: float,
                              quote_change: float, agreeing_exchanges: int) -> float:
        move_score = min(btc_move_pct / max(self.min_price_diff * 3, 0.001), 1.0) * 0.4
        ideal_delay = min(8.0, self.max_delay)
        delay_score = max(0.0, 1.0 - abs(delay - ideal_delay) / max(ideal_delay, 1.0)) * 0.25
        lag_score = (1.0 - min(abs(quote_change) / max(self.max_probability_followthrough, 0.005), 1.0)) * 0.2
        consensus_score = min(agreeing_exchanges / max(self.min_consensus_exchanges, 1), 1.0) * 0.15
        return min(move_score + delay_score + lag_score + consensus_score, 1.0)

    def _assess_risk(self, confidence: float, delay: float) -> str:
        if confidence >= 0.85 and delay <= 10:
            return "low"
        if confidence >= 0.7 and delay <= self.max_delay:
            return "medium"
        return "high"

    async def _notify_callbacks(self, opportunity: Opportunity):
        for callback in self.callbacks:
            try:
                await callback(opportunity)
            except Exception:
                logger.exception("Opportunity callback error")

    def get_recent_opportunities(self, minutes: int = 60) -> List[Opportunity]:
        cutoff = time.time() - minutes * 60
        return [opp for opp in self.opportunities if opp.timestamp >= cutoff]

    def get_success_rate(self) -> float:
        recent = self.get_recent_opportunities(240)
        if not recent:
            return 0.0
        return sum(opp.confidence for opp in recent) / len(recent) * 0.85
