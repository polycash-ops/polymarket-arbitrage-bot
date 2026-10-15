"""
Trade Executor - Executes trades on Polymarket
Handles both paper trading and live trading with risk management
"""
import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import logging

from .opportunity_detector import Opportunity

logger = logging.getLogger(__name__)

class TradeStatus(Enum):
    PENDING = "pending"
    EXECUTED = "executed" 
    FAILED = "failed"
    CANCELLED = "cancelled"
    SETTLED = "settled"

@dataclass
class Trade:
    id: str
    opportunity: Opportunity
    action: str  # 'buy_yes', 'buy_no'
    amount: float
    expected_price: float
    status: TradeStatus = TradeStatus.PENDING
    executed_price: Optional[float] = None
    executed_at: Optional[float] = None
    profit_loss: Optional[float] = None
    notes: str = ""
    market_id: Optional[str] = None
    outcome_index: int = 0
    shares: float = 0.0
    resolved: bool = False
    stats_recorded: bool = False

@dataclass
class TradingStats:
    total_trades: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    total_profit: float = 0.0
    total_volume: float = 0.0
    win_rate: float = 0.0
    avg_profit_per_trade: float = 0.0
    max_drawdown: float = 0.0
    current_balance: float = 10000.0  # Starting balance

class TradeExecutor:
    def __init__(self, config: dict, paper_trading: bool = True):
        self.config = config
        if not paper_trading:
            raise RuntimeError('Live trading is hard-blocked in this repository; initialize TradeExecutor in paper mode only.')
        self.paper_trading = True
        self.session: Optional[aiohttp.ClientSession] = None
        self._settlement_task = None
        
        # Trading parameters
        self.max_position_size = config.get('max_position_size', 1000)  # $1000 max per trade
        self.min_position_size = config.get('min_position_size', 100)   # $100 min per trade
        self.risk_per_trade = config.get('risk_per_trade', 0.02)        # 2% of balance max risk
        
        # State
        self.trades: List[Trade] = []
        self.stats = TradingStats()
        self.callbacks = []
        
        # Paper trading simulation
        self.paper_balance = 10000.0
        self.paper_positions: Dict[str, float] = {}
        
        logger.info(f"🎯 Trade Executor initialized - Mode: {'PAPER' if paper_trading else 'LIVE'}")
        
    def add_callback(self, callback):
        """Add callback for trade events"""
        self.callbacks.append(callback)
        
    async def start(self):
        """Start the trade executor"""
        self.session = aiohttp.ClientSession()
        self._settlement_task = asyncio.create_task(self._settlement_loop())
        logger.info("Trade Executor started in paper-only mode; settlement monitor enabled")
        
    async def stop(self):
        """Stop the trade executor"""
        if self._settlement_task:
            self._settlement_task.cancel()
            try:
                await self._settlement_task
            except asyncio.CancelledError:
                pass
        if self.session:
            await self.session.close()
        logger.info("Trade Executor stopped")
        
    async def execute_opportunity(self, opportunity: Opportunity) -> Optional[Trade]:
        """Create a paper fill only when the selected market has usable live quotes."""
        if not opportunity.market_id:
            logger.info("Paper execution skipped: opportunity has no market ID")
            return None
        if opportunity.yes_bid is None or opportunity.yes_ask is None:
            logger.info("Paper execution skipped: Polymarket bid/ask unavailable")
            return None
        if opportunity.recommended_action == "buy_yes":
            entry_price = float(opportunity.yes_ask)
            outcome_index = int(opportunity.yes_outcome_index)
        elif opportunity.recommended_action == "buy_no":
            entry_price = 1.0 - float(opportunity.yes_bid)
            outcome_index = 1 - int(opportunity.yes_outcome_index)
        else:
            logger.info("Paper execution skipped: action is not buy_yes/buy_no")
            return None
        if not (0.001 <= entry_price < 1.0):
            logger.info("Paper execution skipped: invalid entry ask %.4f", entry_price)
            return None
        if not self._risk_check(opportunity):
            logger.info("Paper execution rejected by risk checks: %s", opportunity.recommended_action)
            return None
        position_size = self._calculate_position_size(opportunity)
        if position_size < self.min_position_size:
            logger.info("Paper execution rejected: position size $%.2f below minimum", position_size)
            return None
        trade = Trade(
            id=f"trade_{int(time.time())}_{len(self.trades)}",
            opportunity=opportunity,
            action=opportunity.recommended_action,
            amount=position_size,
            expected_price=entry_price,
            market_id=opportunity.market_id,
            outcome_index=outcome_index,
        )
        self.trades.append(trade)
        success = await self._execute_paper_trade(trade)
        self._update_stats(trade)
        await self._notify_callbacks(trade)
        return trade if success else None

    async def _execute_paper_trade(self, trade: Trade) -> bool:
        """Simulate a fill at the observed ask; never invent a winning result."""
        try:
            if trade.amount > self.paper_balance:
                trade.status = TradeStatus.FAILED
                trade.notes = "Insufficient available paper balance"
                return False
            await asyncio.sleep(0.05)
            trade.shares = trade.amount / trade.expected_price
            trade.executed_price = trade.expected_price
            trade.executed_at = time.time()
            trade.status = TradeStatus.EXECUTED
            trade.notes = "Paper fill at observed Polymarket ask; awaiting market settlement"
            self.paper_balance -= trade.amount
            logger.info(
                "PAPER FILL id=%s market=%s action=%s stake=$%.2f ask=%.4f shares=%.4f "
                "available_balance=$%.2f; P/L remains unsettled",
                trade.id, trade.market_id, trade.action, trade.amount,
                trade.executed_price, trade.shares, self.paper_balance
            )
            return True
        except Exception as exc:
            logger.exception("Paper fill failed: %s", exc)
            trade.status = TradeStatus.FAILED
            trade.notes = f"Paper fill error: {exc}"
            return False

    async def _settlement_loop(self):
        """Poll Gamma for final outcomes and settle paper positions only when resolved."""
        url = "https://gamma-api.polymarket.com/markets"
        while True:
            try:
                await asyncio.sleep(10)
                if not self.session:
                    continue
                open_trades = [
                    trade for trade in self.trades
                    if trade.status == TradeStatus.EXECUTED and not trade.resolved and trade.market_id
                ]
                for trade in open_trades:
                    try:
                        async with self.session.get(url, params={"slug": trade.market_id, "limit": 5}) as response:
                            if response.status != 200:
                                continue
                            payload = await response.json()
                        markets = payload if isinstance(payload, list) else []
                        market = next((m for m in markets if isinstance(m, dict) and
                                       str(m.get("slug") or m.get("id") or "") == trade.market_id), None)
                        if not market and trade.market_id.isdigit():
                            async with self.session.get(url, params={"id": trade.market_id, "limit": 5}) as response:
                                if response.status == 200:
                                    fallback = await response.json()
                                    if isinstance(fallback, list):
                                        market = next((m for m in fallback if isinstance(m, dict) and
                                                       str(m.get("id") or "") == trade.market_id), None)
                        if not market or market.get("closed") is not True:
                            continue
                        outcomes = market.get("outcomes", [])
                        prices = market.get("outcomePrices", [])
                        if isinstance(outcomes, str):
                            outcomes = json.loads(outcomes)
                        if isinstance(prices, str):
                            prices = json.loads(prices)
                        if not isinstance(prices, list) or len(prices) <= trade.outcome_index:
                            continue
                        try:
                            final_price = float(prices[trade.outcome_index])
                        except (TypeError, ValueError):
                            continue
                        if final_price >= 0.99:
                            payout = trade.shares
                        elif final_price <= 0.01:
                            payout = 0.0
                        else:
                            # Closed market without a definitive binary result: wait for final data.
                            continue
                        trade.profit_loss = payout - trade.amount
                        trade.resolved = True
                        trade.status = TradeStatus.SETTLED
                        trade.notes = "Settled from Polymarket Gamma final outcome"
                        self.paper_balance += payout
                        self._update_stats(trade)
                        await self._notify_callbacks(trade)
                        logger.info(
                            "PAPER SETTLEMENT id=%s market=%s outcome=%s payout=$%.2f P/L=$%.2f balance=$%.2f",
                            trade.id, trade.market_id, outcomes[trade.outcome_index]
                            if isinstance(outcomes, list) and len(outcomes) > trade.outcome_index else trade.outcome_index,
                            payout, trade.profit_loss, self.paper_balance
                        )
                    except Exception as exc:
                        logger.warning("Settlement check failed for %s: %s", trade.id, exc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Paper settlement loop error")
                await asyncio.sleep(5)

    async def _execute_live_trade(self, trade: Trade) -> bool:
        """Execute live trade on Polymarket"""
        logger.warning("🚫 LIVE TRADING NOT IMPLEMENTED - Use paper trading for now")
        
        # TODO: Implement actual Polymarket API integration
        # This would involve:
        # 1. Authentication with Polymarket
        # 2. Finding the correct market
        # 3. Placing buy/sell orders
        # 4. Handling order execution
        # 5. Error handling and retries
        
        trade.status = TradeStatus.FAILED
        trade.notes = "Live trading not implemented"
        return False
        
    def _risk_check(self, opportunity: Opportunity) -> bool:
        """Perform risk management checks"""
        
        # Check minimum confidence
        if opportunity.confidence < self.config.get('min_confidence', 0.7):
            return False
            
        # Check if we have enough balance
        required_amount = self._calculate_position_size(opportunity)
        if self.paper_trading and required_amount > self.paper_balance * 0.1:  # Max 10% of balance per trade
            return False
            
        # Check maximum daily trades
        today_trades = len([t for t in self.trades 
                          if time.time() - t.opportunity.timestamp < 86400])
        if today_trades >= self.config.get('max_daily_trades', 50):
            return False
            
        # Check if similar opportunity was recently traded
        recent_similar = [t for t in self.trades[-10:] 
                         if t.action == opportunity.recommended_action 
                         and time.time() - t.opportunity.timestamp < 300]  # 5 minutes
        if len(recent_similar) >= 2:
            return False
            
        return True
        
    def _calculate_position_size(self, opportunity: Opportunity) -> float:
        """Calculate optimal position size based on Kelly criterion and risk management"""
        
        # Base position size (percentage of balance)
        base_percentage = 0.05  # 5% of balance
        
        # Adjust based on confidence
        confidence_multiplier = opportunity.confidence  # 0.7-1.0
        
        # Adjust based on expected profit
        profit_multiplier = min(opportunity.expected_profit / 2.0, 2.0)  # Cap at 2x
        
        # Calculate position size
        if self.paper_trading:
            available_balance = self.paper_balance
        else:
            available_balance = self.stats.current_balance
            
        position_size = available_balance * base_percentage * confidence_multiplier * profit_multiplier
        
        # Apply limits
        position_size = max(position_size, self.min_position_size)
        position_size = min(position_size, self.max_position_size)
        position_size = min(position_size, available_balance * 0.1)  # Never more than 10% of balance
        
        return round(position_size, 2)
        
    def _update_stats(self, trade: Trade):
        """Only settled outcomes contribute to win rate and realized P/L."""
        if trade.status == TradeStatus.FAILED:
            if not trade.stats_recorded:
                self.stats.failed_trades += 1
                trade.stats_recorded = True
            return
        if not trade.resolved or trade.stats_recorded:
            self.stats.current_balance = self.paper_balance
            return
        trade.stats_recorded = True
        self.stats.total_trades += 1
        self.stats.total_volume += trade.amount
        if trade.profit_loss is not None:
            self.stats.total_profit += trade.profit_loss
            if trade.profit_loss > 0:
                self.stats.successful_trades += 1
        self.stats.win_rate = (
            self.stats.successful_trades / self.stats.total_trades
            if self.stats.total_trades else 0.0
        )
        self.stats.avg_profit_per_trade = (
            self.stats.total_profit / self.stats.total_trades
            if self.stats.total_trades else 0.0
        )
        self.stats.current_balance = self.paper_balance

    async def _notify_callbacks(self, trade: Trade):
        """Notify all callbacks about trade events"""
        for callback in self.callbacks:
            try:
                await callback(trade)
            except Exception as e:
                logger.error(f"❌ Trade callback error: {e}")
                
    def get_stats(self) -> TradingStats:
        """Get current trading statistics"""
        return self.stats
        
    def get_recent_trades(self, hours: int = 24) -> List[Trade]:
        """Get trades from last N hours"""
        cutoff_time = time.time() - (hours * 3600)
        return [trade for trade in self.trades 
                if trade.opportunity.timestamp >= cutoff_time]
                
    def get_performance_report(self) -> Dict:
        """Get detailed performance report"""
        recent_trades = self.get_recent_trades(24)
        
        settled_today = [t for t in recent_trades if t.resolved and t.profit_loss is not None]
        settled_all = [t for t in self.trades if t.resolved and t.profit_loss is not None]
        return {
            'current_balance': self.stats.current_balance,
            'total_profit': self.stats.total_profit,
            'win_rate': self.stats.win_rate,
            'total_trades': self.stats.total_trades,
            'open_trades': sum(1 for t in self.trades if t.status == TradeStatus.EXECUTED and not t.resolved),
            'failed_trades': self.stats.failed_trades,
            'avg_profit_per_trade': self.stats.avg_profit_per_trade,
            'trades_today': len(settled_today),
            'profit_today': sum(t.profit_loss for t in settled_today),
            'best_trade': max((t.profit_loss for t in settled_all), default=0),
            'worst_trade': min((t.profit_loss for t in settled_all), default=0)
        }