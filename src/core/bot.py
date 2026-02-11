"""
Main Trading Bot Class
Orchestrates all components for AI-enhanced arbitrage
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from .config import BotConfig
from data.market_monitor import MarketMonitor
from data.opportunity_detector import OpportunityDetector
from ai.pattern_analyzer import PatternAnalyzer
from ai.sentiment_analyzer import SentimentAnalyzer
from execution.trade_executor import TradeExecutor
from monitoring.performance_tracker import PerformanceTracker


class TradingBot:
    """
    Main trading bot that replicates and improves 0x8dxd's strategy
    """
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.running = False
        
        # Core components
        self.market_monitor = MarketMonitor(config)
        self.opportunity_detector = OpportunityDetector(config)
        self.pattern_analyzer = PatternAnalyzer(config)
        self.sentiment_analyzer = SentimentAnalyzer(config)
        self.trade_executor = TradeExecutor(config)
        self.performance_tracker = PerformanceTracker(config)
        
        # State tracking
        self.trades_today = 0
        self.daily_pnl = 0.0
        self.win_streak = 0
        self.last_trade_time = None
        
        self.logger.info("🤖 TradingBot initialized")
        if config.trading.paper_mode:
            self.logger.info("📝 Paper trading mode - No real money")
        else:
            self.logger.warning("💰 LIVE TRADING mode - Real money at risk!")
    
    async def start(self):
        """Start the trading bot main loop"""
        self.running = True
        self.logger.info("🚀 Starting bot main loop...")
        
        # Start background tasks
        tasks = await self._start_background_tasks()
        
        try:
            # Main trading loop
            await self._main_loop()
        finally:
            # Cleanup
            self.running = False
            for task in tasks:
                task.cancel()
            
            self.logger.info("🛑 Bot stopped")
    
    async def _start_background_tasks(self) -> List[asyncio.Task]:
        """Start all background monitoring tasks"""
        tasks = [
            asyncio.create_task(self.market_monitor.start()),
            asyncio.create_task(self._performance_monitor()),
            asyncio.create_task(self._heartbeat()),
        ]
        
        self.logger.info("📡 Background tasks started")
        return tasks
    
    async def _main_loop(self):
        """Main trading logic loop"""
        self.logger.info("🔄 Entering main trading loop")
        
        while self.running:
            try:
                # Get current market data
                market_data = await self.market_monitor.get_latest_data()
                
                if not market_data:
                    await asyncio.sleep(0.1)
                    continue
                
                # Detect arbitrage opportunities
                opportunities = await self.opportunity_detector.find_opportunities(market_data)
                
                if not opportunities:
                    await asyncio.sleep(0.1)  
                    continue
                
                # Analyze each opportunity with AI
                for opp in opportunities:
                    if await self._should_trade(opp, market_data):
                        await self._execute_trade(opp)
                
                await asyncio.sleep(0.05)  # 50ms loop
                
            except Exception as e:
                self.logger.error(f"❌ Error in main loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _should_trade(self, opportunity: Dict, market_data: Dict) -> bool:
        """
        Decide if we should take this opportunity
        Uses AI analysis + risk management
        """
        
        # Basic filters
        if opportunity['edge'] < self.config.trading.min_edge_threshold:
            return False
            
        if opportunity['size'] > self.config.trading.max_position_size:
            return False
        
        # Rate limiting
        if self.trades_today >= self.config.trading.max_trades_per_hour:
            return False
        
        # AI Analysis
        pattern_confidence = await self.pattern_analyzer.analyze(opportunity, market_data)
        sentiment_score = await self.sentiment_analyzer.get_market_sentiment()
        
        combined_confidence = (pattern_confidence + sentiment_score) / 2
        
        if combined_confidence < self.config.ai.prediction_confidence_threshold:
            self.logger.debug(f"🤔 Low AI confidence: {combined_confidence:.2f}")
            return False
        
        self.logger.info(f"✅ Trade approved - Edge: {opportunity['edge']:.1%}, "
                        f"Confidence: {combined_confidence:.2f}")
        return True
    
    async def _execute_trade(self, opportunity: Dict):
        """Execute the trade"""
        try:
            result = await self.trade_executor.execute(opportunity)
            
            if result['success']:
                self.trades_today += 1
                self.daily_pnl += result['pnl']
                
                if result['pnl'] > 0:
                    self.win_streak += 1
                else:
                    self.win_streak = 0
                
                self.logger.info(f"💰 Trade executed: PnL ${result['pnl']:.2f}, "
                                f"Trades today: {self.trades_today}")
                
                # Track performance
                await self.performance_tracker.record_trade(result)
            
        except Exception as e:
            self.logger.error(f"❌ Trade execution failed: {e}")
    
    async def _performance_monitor(self):
        """Monitor performance and alert if needed"""
        while self.running:
            try:
                stats = await self.performance_tracker.get_daily_stats()
                
                # Log performance every hour
                self.logger.info(f"📊 Performance: PnL ${stats['daily_pnl']:.2f}, "
                                f"Win Rate: {stats['win_rate']:.1%}, "
                                f"Trades: {stats['trades_count']}")
                
                # Check for alerts
                if stats['drawdown'] > self.config.monitoring.max_drawdown_alert:
                    self.logger.warning(f"🚨 High drawdown: {stats['drawdown']:.1%}")
                
                await asyncio.sleep(3600)  # Check every hour
                
            except Exception as e:
                self.logger.error(f"❌ Performance monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def _heartbeat(self):
        """Send periodic heartbeat logs"""
        while self.running:
            self.logger.info(f"💓 Bot alive - Daily PnL: ${self.daily_pnl:.2f}, "
                            f"Trades: {self.trades_today}")
            await asyncio.sleep(1800)  # Every 30 minutes
    
    async def stop(self):
        """Stop the bot gracefully"""
        self.logger.info("🛑 Stopping bot...")
        self.running = False