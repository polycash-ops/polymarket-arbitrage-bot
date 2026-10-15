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
        logger.info("✅ Trade Executor started")
        
    async def stop(self):
        """Stop the trade executor"""
        if self.session:
            await self.session.close()
        logger.info("🛑 Trade Executor stopped")
        
    async def execute_opportunity(self, opportunity: Opportunity) -> Optional[Trade]:
        """Execute a trading opportunity"""
        
        # Risk management checks
        if not self._risk_check(opportunity):
            logger.warning(f"❌ Risk check failed for opportunity: {opportunity.recommended_action}")
            return None
            
        # Calculate position size
        position_size = self._calculate_position_size(opportunity)
        
        if position_size < self.min_position_size:
            logger.warning(f"❌ Position size too small: ${position_size:.2f}")
            return None
            
        # Create trade
        trade = Trade(
            id=f"trade_{int(time.time())}_{len(self.trades)}",
            opportunity=opportunity,
            action=opportunity.recommended_action,
            amount=position_size,
            expected_price=0.5  # Simplified for demo
        )
        
        self.trades.append(trade)
        
        # This fork is paper-only. Never route an opportunity to live execution.
        success = await self._execute_paper_trade(trade)
            
        # Update stats
        self._update_stats(trade)
        
        # Notify callbacks
        await self._notify_callbacks(trade)
        
        return trade if success else None
        
    async def _execute_paper_trade(self, trade: Trade) -> bool:
        """Execute paper trade (simulation)"""
        try:
            logger.info(f"📝 PAPER TRADE: {trade.action} ${trade.amount:.2f}")
            
            # Simulate execution delay
            await asyncio.sleep(0.1)
            
            # Simulate success rate based on opportunity confidence
            success_probability = trade.opportunity.confidence * 0.9  # 90% max success
            
            # For demo, always succeed with high confidence opportunities
            if trade.opportunity.confidence > 0.7:
                trade.status = TradeStatus.EXECUTED
                trade.executed_price = 0.5  # Simplified
                trade.executed_at = time.time()
                
                # Calculate simulated profit
                expected_return = trade.opportunity.expected_profit / 100  # Convert percentage
                trade.profit_loss = trade.amount * expected_return
                
                # Update paper balance
                self.paper_balance += trade.profit_loss
                
                logger.info(
                    f"✅ PAPER TRADE EXECUTED: {trade.id} - "
                    f"Profit: ${trade.profit_loss:.2f}, Balance: ${self.paper_balance:.2f}"
                )
                return True
            else:
                trade.status = TradeStatus.FAILED
                trade.notes = "Low confidence opportunity"
                trade.profit_loss = -trade.amount * 0.1  # Small loss
                self.paper_balance += trade.profit_loss
                
                logger.info(f"❌ PAPER TRADE FAILED: {trade.id} - Low confidence")
                return False
                
        except Exception as e:
            logger.error(f"❌ Paper trade execution error: {e}")
            trade.status = TradeStatus.FAILED
            trade.notes = f"Execution error: {str(e)}"
            return False
            
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
        """Update trading statistics"""
        self.stats.total_trades += 1
        self.stats.total_volume += trade.amount
        
        if trade.status == TradeStatus.EXECUTED:
            self.stats.successful_trades += 1
            if trade.profit_loss:
                self.stats.total_profit += trade.profit_loss
        else:
            self.stats.failed_trades += 1
            
        # Calculate derived stats
        if self.stats.total_trades > 0:
            self.stats.win_rate = self.stats.successful_trades / self.stats.total_trades
            self.stats.avg_profit_per_trade = self.stats.total_profit / self.stats.total_trades
            
        # Update balance
        if self.paper_trading:
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
        
        return {
            'current_balance': self.stats.current_balance,
            'total_profit': self.stats.total_profit,
            'win_rate': self.stats.win_rate,
            'total_trades': self.stats.total_trades,
            'avg_profit_per_trade': self.stats.avg_profit_per_trade,
            'trades_today': len(recent_trades),
            'profit_today': sum(t.profit_loss or 0 for t in recent_trades),
            'best_trade': max((t.profit_loss or 0 for t in self.trades), default=0),
            'worst_trade': min((t.profit_loss or 0 for t in self.trades), default=0)
        }